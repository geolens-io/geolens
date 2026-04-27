---
phase: 212-core-settings-decouple
plan: 04
type: execute
wave: 4
depends_on: ["212-03"]
files_modified: []
autonomous: true
requirements: [LAYER-01]
requirements_addressed: [LAYER-01]
tags: [verification, alembic, pytest, ruff, open-core]

must_haves:
  truths:
    - "Alembic reports no schema drift after the relocation (`alembic check` exits 0 with `No new upgrade operations.` or equivalent)."
    - "The full backend test suite (excluding `perf`) passes — at least 1965 tests collected, all green."
    - "Ruff lint and format checks pass cleanly across `app/`, `tests/`, and `alembic/`."
    - "All five ROADMAP.md success criteria for Phase 212 are met (zero core->settings imports; PersistentConfig + admin Settings UI behaviors preserved; public URL precedence preserved; baseline green; audit findings closed)."
    - "The phase exit gate is unambiguous: every command in `<verification>` exits 0."
  artifacts:
    - path: ".planning/phases/212-core-settings-decouple/212-04-SUMMARY.md"
      provides: "Phase verification gate evidence — captured exit codes, pytest summary, alembic output, ruff output"
      contains: "VERIFICATION RESULT"
  key_links:
    - from: "Plan 04 verification step"
      to: "ROADMAP.md Phase 212 Success Criteria 1-5"
      via: "1:1 mapping in `<verification>` section below"
      pattern: "SC#"
---

<objective>
Run the phase-level verification gate: alembic schema-drift check, full pytest suite, ruff lint, and the architecture guard. No production files are modified by this plan — it is purely a verification step that produces an evidence file (`212-04-SUMMARY.md`) capturing the result of each command.

Purpose: D-08 mandates `alembic check` as the no-migration proof. D-09 mandates a full pytest run as the acceptance gate. Plans 01-03 made all the changes; this plan proves they hold up against the 1965-test baseline before `/gsd-verify-work` runs phase verification. If any check fails here, the failure is the planner/executor's signal to fix-forward in this phase, not to defer.

Output: An evidence summary at `.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md` documenting the exit code and key output of each verification command. No source-tree files are created or modified.

**Note on `pyright`:** RESEARCH.md and VALIDATION.md (V-13) mention type checking, but `backend/pyproject.toml`'s `[dependency-groups].dev` does NOT include `pyright` or `mypy` — the project does not run a static type checker. [VERIFIED 2026-04-27 — dev deps are: pytest, pytest-asyncio, httpx, ruff, jsonschema, pytest-cov, bandit, pip-audit, moto, fakeredis, pystac.] V-13 is therefore N/A for this phase; ruff is the canonical static check. This plan does NOT run pyright; it runs ruff instead.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/212-core-settings-decouple/212-CONTEXT.md
@.planning/phases/212-core-settings-decouple/212-RESEARCH.md
@.planning/phases/212-core-settings-decouple/212-VALIDATION.md
@.planning/phases/212-core-settings-decouple/212-01-SUMMARY.md
@.planning/phases/212-core-settings-decouple/212-02-SUMMARY.md
@.planning/phases/212-core-settings-decouple/212-03-SUMMARY.md

<interfaces>
<!-- Verification commands (each must exit 0). Sourced from VALIDATION.md "Sampling Rate" / "Validation Sign-Off" and RESEARCH.md "Verification commands". -->

```bash
# 1. Alembic schema-drift check (D-08 / V-11)
cd backend && uv run alembic check

# 2. Full backend test suite (D-09 / V-12). pyproject.toml addopts already excludes -m perf; this is the canonical CI invocation.
cd backend && uv run pytest --tb=short

# 3. Ruff lint (replaces V-13's pyright reference; pyright is not a dev dep — see objective note)
cd backend && uv run ruff check app/ tests/ alembic/
cd backend && uv run ruff format --check app/ tests/ alembic/

# 4. Final layering-finding gate: V-14 + ROADMAP SC#1
git grep -n "from app\.modules\.settings" -- backend/app/core/    # MUST be empty
git grep -n "from app\.modules\.settings\.models" -- backend/      # MUST be empty
test ! -e backend/app/modules/settings/models.py                   # MUST exit 0

# 5. Architecture guard test (V-09)
cd backend && uv run pytest tests/test_layering.py -v -m architecture
```

<!-- Mapping of these commands to ROADMAP.md Phase 212 Success Criteria: -->
<!-- SC#1: zero AppSetting imports under core/  -> commands 4a/4b -->
<!-- SC#2: PersistentConfig + admin Settings UI behaviors preserved  -> command 2 (test_persistent_config.py + test_settings_router.py + test_settings_admin.py within full suite) -->
<!-- SC#3: public_urls.py precedence preserved  -> command 2 (test_public_urls.py within full suite) -->
<!-- SC#4: 1965-test baseline green  -> command 2 (full suite) -->
<!-- SC#5: audit's specific findings (core/persistent_config.py:30, core/public_urls.py:14) no longer reproduce  -> command 4a + command 5 (architecture guard) -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 04-01: Run phase verification gate and capture evidence to SUMMARY</name>
  <files>.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md</files>
  <read_first>
    - .planning/phases/212-core-settings-decouple/212-VALIDATION.md (Sampling Rate / Phase gate; V-09 through V-14)
    - .planning/phases/212-core-settings-decouple/212-RESEARCH.md (Verification commands section)
    - .planning/ROADMAP.md (Phase 212 Success Criteria — 5 conditions to satisfy)
    - .planning/phases/212-core-settings-decouple/212-CONTEXT.md (D-08 — alembic check; D-09 — full pytest)
  </read_first>
  <action>
Run each verification command in order. Capture the exit code and a brief excerpt of stdout/stderr. If ANY command exits non-zero, STOP and fix-forward in the appropriate plan; do not paper over a failure.

**Step 1 — Alembic schema-drift check (D-08, V-11, ROADMAP SC #1+#5 supporting evidence):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run alembic check
```

Expected: exit 0, output includes "No new upgrade operations." (or alembic 1.13's equivalent zero-diff message). The exact wording is alembic-version-dependent but exit 0 is the gate. If it exits non-zero with `ModuleNotFoundError`, RESEARCH.md Pitfall 1 was missed in Plan 02 — go fix `backend/alembic/env.py:22`. If it exits non-zero with a schema-diff message, RESEARCH.md Pitfall 3 was triggered (`__table_args__` or column types drifted) — review `backend/app/core/db/models.py` against the original `backend/app/modules/settings/models.py` (use `git show` of the pre-Plan-02 commit to retrieve the deleted file's contents).

If `alembic check` reports a database-connection error (no live DB), bring up the DB with `docker compose up -d postgres` (or the project's equivalent — see Makefile) and re-run. The connection error is NOT a passing gate; alembic must be able to compare against the live schema for D-08 to be satisfied.

**Step 2 — Full backend test suite (D-09, V-12, ROADMAP SC #2+#3+#4):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest --tb=short 2>&1 | tee /tmp/212-04-pytest.log
```

`pyproject.toml`'s `addopts = "-m 'not perf'"` ensures the perf marker is excluded by default — this matches CI's invocation. Expected: exit 0, summary line shows `1965 passed` or `≥1965 passed` (the new architecture tests in Plan 03 add 2 more, so the count rises to 1967). Capture the final summary line in the SUMMARY file.

If any test fails, classify by the failure mode:
- `ModuleNotFoundError: app.modules.settings.models` -> Plan 02 missed an importer (re-run Task 02-01's grep gate).
- `ImportError: cannot import name 'AppSetting'` -> Plan 01's class definition is malformed.
- Test collection error in `test_layering.py` -> Plan 03's path math is wrong (check `Path(__file__).resolve().parents[2]`).
- Genuine test failure (assertion, fixture, behavior change) -> regression introduced by relocation; debug PersistentConfig / public_urls / settings router code paths in `core/persistent_config.py` and `core/public_urls.py`.

**Step 3 — Ruff lint and format check (replaces V-13; pyright is not a dev dep):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run ruff check app/ tests/ alembic/
cd /Users/ishiland/Code/geolens/backend && uv run ruff format --check app/ tests/ alembic/
```

Both must exit 0. Ruff catches unused imports (F401) and unresolved imports (F821) — these are the issues a missed migration site would produce. If `ruff check` reports F401 in the new `core/db/models.py`, the imports are wrong; if it reports F821 anywhere, an `AppSetting` reference points to nothing. Note: the alembic env.py uses `# noqa: F401` to suppress unused-import warnings on its side-effect import; that suppression must remain after Plan 02 (verified by Plan 02's acceptance criteria).

**Step 4 — Final ROADMAP success-criteria gates (V-14, SC #1, SC #5):**

```bash
cd /Users/ishiland/Code/geolens

# SC#1 / V-14: zero AppSetting (or any settings-module) imports under backend/app/core/
git grep -n "from app\.modules\.settings" -- backend/app/core/ ; test $? -eq 1

# Comprehensive: zero references to the deleted module path anywhere under backend/
git grep -n "from app\.modules\.settings\.models\|import app\.modules\.settings\.models" -- backend/ ; test $? -eq 1

# D-05 / Plan 02: the old file is deleted
test ! -e backend/app/modules/settings/models.py
```

All three commands must exit 0 (the `test $? -eq 1` idiom inverts `git grep`'s "no-match-is-failure" exit-1 into "no-match-is-success-exit-0" for the gate).

**Step 5 — Architecture guard test (V-09):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
```

Expected: exit 0, "2 passed". This is technically already covered by Step 2 (the full suite includes the architecture tests by default per Plan 03's marker registration), but running it standalone produces a clean evidence line in the SUMMARY for Phase 218's audit.

**Step 6 — Capture evidence to SUMMARY.**

Create `.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md` with this structure (substitute real values):

```markdown
# Phase 212 - Plan 04 Verification Gate Evidence

**Run date:** {ISO timestamp}
**Result:** PASS / FAIL

## Verification Commands

| # | Command | Exit | Key output |
|---|---------|------|------------|
| 1 | `cd backend && uv run alembic check` | 0 | "No new upgrade operations." (or actual output) |
| 2 | `cd backend && uv run pytest --tb=short` | 0 | "1967 passed in N.NNs" (1965 baseline + 2 new architecture tests) |
| 3a | `cd backend && uv run ruff check app/ tests/ alembic/` | 0 | "All checks passed!" (or actual) |
| 3b | `cd backend && uv run ruff format --check app/ tests/ alembic/` | 0 | "N files already formatted" (or actual) |
| 4a | `git grep "from app.modules.settings" -- backend/app/core/` | 1 (no matches) | (empty) |
| 4b | `git grep "from app.modules.settings.models\|import app.modules.settings.models" -- backend/` | 1 (no matches) | (empty) |
| 4c | `test ! -e backend/app/modules/settings/models.py` | 0 | (file does not exist) |
| 5 | `cd backend && uv run pytest tests/test_layering.py -v -m architecture` | 0 | "2 passed" |

## ROADMAP Phase 212 Success Criteria — Status

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `grep -rn "from app.modules.settings" backend/app/core/` returns zero AppSetting imports | PASS | Step 4a |
| 2 | PersistentConfig continues to read/write DB-backed values; admin Settings UI loads/saves all 16 config instances correctly | PASS | Step 2 (test_persistent_config.py + test_settings_router.py + test_settings_admin.py within full suite); plus manual smoke per VALIDATION.md "Manual-Only Verifications" |
| 3 | core/public_urls.py continues to resolve the public base URL with same precedence (request -> DB override -> env var) | PASS | Step 2 (test_public_urls.py within full suite) |
| 4 | The 1965-test backend baseline stays green; no AppSetting-import shimming required | PASS | Step 2 (≥1965 tests passed; D-04/D-05 confirmed no shim) |
| 5 | The audit's "Layering" finding for `core/persistent_config.py:30` and `core/public_urls.py:14` no longer reproduces | PASS | Step 4a + Step 5 (architecture guard catches reintroduction) |

## Manual-Only Verifications Reminder

VALIDATION.md flags one remaining manual smoke test for the executor or reviewer:

- Admin Settings UI smoke (~3 min): `docker compose up -d`, log in as admin, open `/admin/settings`, confirm all 6 tabs load values; toggle one boolean (e.g., Registration Enabled); confirm save returns 200 and the change persists across page reload. This validates ROADMAP SC #2's UI surface beyond the API tests in Step 2.

## Notes

- pyright/mypy NOT run because the project does not include a static type checker in its dev dependencies (verified `backend/pyproject.toml` `[dependency-groups].dev`); ruff (Step 3a/3b) is the canonical static check.
- The architecture guard test scope is NARROW (only `from app.modules.settings`) — see Plan 03 SUMMARY and 212-RESEARCH.md Open Question 1 for the broadening plan in Phase 218.
```

Hard constraints:
- This plan modifies ZERO source files. The only artifact is the SUMMARY at `.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md`.
- If any verification command exits non-zero, stop and fix-forward (in Plan 01, 02, or 03 as appropriate). Do NOT mark this plan PASS with a failure carried over.
- The manual UI smoke (3 min) is documented but NOT auto-executed by this task; the executor or reviewer runs it as the final ROADMAP SC #2 confirmation before `/gsd-verify-work` closes the phase.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && (cd backend && uv run alembic check) && (cd backend && uv run pytest --tb=short -q) && (cd backend && uv run ruff check app/ tests/ alembic/) && (cd backend && uv run ruff format --check app/ tests/ alembic/) && bash -c 'git grep -n "from app\.modules\.settings" -- backend/app/core/; test $? -eq 1' && bash -c 'git grep -n "from app\.modules\.settings\.models\|import app\.modules\.settings\.models" -- backend/; test $? -eq 1' && test ! -e backend/app/modules/settings/models.py && (cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short -q) && test -f .planning/phases/212-core-settings-decouple/212-04-SUMMARY.md</automated>
  </verify>
  <acceptance_criteria>
    - `cd backend && uv run alembic check` exits 0 with no schema diff (NOT a `ModuleNotFoundError`).
    - `cd backend && uv run pytest --tb=short` exits 0; final summary line shows ≥1965 tests passed (post-Plan 03 the count is 1967 because the architecture guard adds 2 tests).
    - `cd backend && uv run ruff check app/ tests/ alembic/` exits 0.
    - `cd backend && uv run ruff format --check app/ tests/ alembic/` exits 0.
    - `git grep -n "from app\.modules\.settings" -- backend/app/core/` returns zero matches (exit 1).
    - `git grep -n "from app\.modules\.settings\.models\|import app\.modules\.settings\.models" -- backend/` returns zero matches (exit 1).
    - `test ! -e backend/app/modules/settings/models.py` exits 0.
    - `cd backend && uv run pytest tests/test_layering.py -v -m architecture` exits 0 with 2 passed.
    - `.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md` exists with the structured evidence table and a `**Result:** PASS` line.
  </acceptance_criteria>
  <done>
    All five ROADMAP Phase 212 success criteria are demonstrably met. The SUMMARY captures exit codes and key output for each command. Phase 212 is ready for `/gsd-verify-work` and ultimately for Phase 218's `/oc-audit` re-run to confirm the Boundary grade improvement.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

This plan is a verification gate. It runs read-only checks (alembic check, pytest, ruff, git grep) and writes a single Markdown evidence file to `.planning/`. No production code changes; no new boundaries introduced.

| Boundary | Description |
|----------|-------------|
| (none) | Pure verification; no runtime impact. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-212-01 (carryover) | T (Tampering) — false-pass gate | The verification gate itself | mitigate | Each verification command is independently verifiable (`alembic check` against the live DB, full pytest run, ruff against the source tree, `git grep` against the working tree). The SUMMARY reports exit codes and stdout excerpts that can be re-run by Phase 218 or any reviewer. The combined gate covers ROADMAP SC #1-#5 with explicit 1:1 mapping (see `<interfaces>` block). |
| T-212-02 (carryover) | E (Elevation via skipping the gate) | Phase exit | accept | If a contributor merges without running this plan, `/gsd-verify-work` will catch the missing SUMMARY artifact and Phase 218's audit re-run will catch the reintroduced finding. The plan is the proof, not the policy. |
| T-212-03 | INFO — no new external surface | (none) | accept | This plan modifies no production files. |
</threat_model>

<verification>
- ROADMAP SC #1 verified by `git grep -n "from app\.modules\.settings" -- backend/app/core/` returning zero matches (Step 4a above).
- ROADMAP SC #2 verified by `test_persistent_config.py`, `test_settings_router.py`, `test_settings_admin.py` passing within the full suite (Step 2). Manual UI smoke (~3 min) documented in SUMMARY for the reviewer.
- ROADMAP SC #3 verified by `test_public_urls.py` passing within the full suite (Step 2).
- ROADMAP SC #4 verified by ≥1965 tests passing in the full suite (Step 2).
- ROADMAP SC #5 verified by Step 4a (zero matches) AND Step 5 (architecture guard test passes — proving any reintroduction would be caught).
- D-08 (no migration generated) verified by `alembic check` exit 0 with no schema diff (Step 1).
- D-09 (1965-test baseline) verified by Step 2.
</verification>

<success_criteria>
- All five ROADMAP Phase 212 success criteria are demonstrably met with command-level evidence in `.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md`.
- Phase 212 is ready for orchestrator-level `/gsd-verify-work` and for Phase 218's `/oc-audit` re-run.
- The phase introduced zero behavior change at the wire level (HTTP contract unchanged, DB schema unchanged) — only the Python module path of `AppSetting` and a new architecture guard test.
</success_criteria>

<output>
After completion, the SUMMARY at `.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md` is the artifact. It must contain:
- A `**Result:** PASS` (or `FAIL` with diagnostic notes) header.
- The structured evidence table mapping each verification command to its exit code and a one-line stdout excerpt.
- The ROADMAP Phase 212 SC#1-SC#5 status table.
- A reminder of the manual UI smoke that VALIDATION.md flagged for the reviewer.
- A note that pyright was not run because it is not a project dev dependency (ruff is the canonical static check).
</output>
