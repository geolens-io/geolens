---
phase: 213-catalog-authz-relocate
plan: 04
type: execute
wave: 4
depends_on: ["213-03"]
files_modified: []
autonomous: true
requirements: [LAYER-02]
requirements_addressed: [LAYER-02]
tags: [verification, alembic, pytest, ruff, open-core]

must_haves:
  truths:
    - "D-10: Alembic reports no schema drift after the relocation — `cd backend && uv run alembic check` exits 0 with 'no new operations' (or alembic 1.13's equivalent zero-diff message). The `app_settings`/`catalog.users`/`catalog.dataset_grants`/`catalog.records` tables are unchanged because the relocation is pure Python."
    - "D-11: The full backend test suite (excluding `perf`) passes against the post-Phase-212 baseline (≥1999 passing per RESEARCH.md A2; CONTEXT.md mentions 1965 but RESEARCH overrides with the live count of 1999)."
    - "Ruff lint and format checks pass cleanly across `app/`, `tests/`, and `alembic/`."
    - "All four ROADMAP.md success criteria for Phase 213 are met: SC#1 (visibility.py deleted, all 26 callers migrated), SC#2 (RBAC parity across search/tile/feature/STAC/OGC endpoints), SC#3 (1965-test baseline stays green — actually ≥1999), SC#4 (`git grep auth.visibility` returns zero matches across the repo)."
    - "All 4 architecture-guard tests pass on host: 2 from Phase 212 + 2 new from Phase 213 (Plan 03)."
    - "The phase exit gate is unambiguous: every command in `<verification>` exits 0; the SUMMARY captures exit codes and key output for each."
    - "D-13: No frontend files were modified in this phase — `git diff --name-only` against the merge-base shows zero entries under `frontend/`. No `make openapi-check` regeneration required."
  artifacts:
    - path: ".planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md"
      provides: "Phase verification gate evidence — captured exit codes, pytest summary, alembic output, ruff output, ROADMAP SC mapping"
      contains: "VERIFICATION RESULT"
  key_links:
    - from: "Plan 04 verification step"
      to: "ROADMAP.md Phase 213 Success Criteria 1-4"
      via: "1:1 mapping in `<verification>` section below"
      pattern: "SC#"
---

<objective>
Run the phase-level verification gate: alembic schema-drift check, full pytest suite, ruff lint+format, ROADMAP success-criteria gates, and the architecture-guard standalone run. NO production files are modified by this plan — it is purely a verification step that produces an evidence file (`213-04-SUMMARY.md`) capturing the result of each command.

Purpose: D-10 mandates `alembic check` as the no-migration proof. D-11 mandates a full pytest run as the acceptance gate. Plans 01-03 made all the changes; this plan proves they hold up against the ≥1999-test baseline and the four ROADMAP success criteria before `/gsd-verify-work` runs phase verification. If any check fails here, the failure is the planner/executor's signal to fix-forward in this phase, not to defer.

Output: An evidence summary at `.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md` documenting the exit code and key output of each verification command. NO source-tree files are created or modified.

**Note on `pyright`:** RESEARCH.md confirms `backend/pyproject.toml`'s `[dependency-groups].dev` does NOT include `pyright` or `mypy` — the project does not run a static type checker. Ruff (Step 3) is the canonical static check. This plan does NOT run pyright; it runs ruff instead. (Phase 212-04-SUMMARY.md established this decision.)
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
@.planning/phases/213-catalog-authz-relocate/213-CONTEXT.md
@.planning/phases/213-catalog-authz-relocate/213-RESEARCH.md
@.planning/phases/213-catalog-authz-relocate/213-VALIDATION.md
@.planning/phases/213-catalog-authz-relocate/213-01-SUMMARY.md
@.planning/phases/213-catalog-authz-relocate/213-02-SUMMARY.md
@.planning/phases/213-catalog-authz-relocate/213-03-SUMMARY.md
@.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md

<interfaces>
<!-- Verification commands (each must exit 0). Sourced from VALIDATION.md "Sampling Rate" / "Validation Sign-Off" and RESEARCH.md "Verification commands". -->
<!-- Mirrors Phase 212-04 structure verbatim; only the SC list and grep targets are swapped. -->

```bash
# 1. Alembic schema-drift check (D-10 / VALIDATION row 213-04-01)
cd backend && uv run alembic check

# 2. Full backend test suite (D-11 / VALIDATION row 213-02-02 / ROADMAP SC#2 + SC#3).
docker compose exec api uv run pytest -m 'not perf' --tb=short -q
# Fallback (host) if docker compose is unavailable:
#   cd backend && uv run pytest -m 'not perf' --tb=short -q

# 3. Ruff lint + format
cd backend && uv run ruff check .
cd backend && uv run ruff format --check .

# 4. ROADMAP SC#1 specific gate: zero `from|import app.modules.auth.visibility` import lines
git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/    # MUST exit 1 (no matches)

# 5. ROADMAP SC#1 specific gate: the source file is deleted
test ! -e backend/app/modules/auth/visibility.py                                  # MUST exit 0

# 6. ROADMAP SC#4 specific gate: broader `auth.visibility` reference scan, excluding the test file
git grep -nE "auth\.visibility|from app\.modules\.auth\.visibility" -- backend/ ':!backend/tests/test_layering.py'    # MUST exit 1 (no matches)

# 7. Architecture guard standalone (4 tests: 2 Phase 212 + 2 Phase 213)
cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
# Expected: 4 passed (on host with .git/) OR 4 skipped (inside container without .git/) — both acceptable per Pitfall 5

# 8. Frontend untouched (D-13)
git diff --name-only $(git merge-base HEAD origin/main 2>/dev/null || git rev-parse HEAD~4)..HEAD -- frontend/
# Must produce zero output.
```

<!-- Mapping of these commands to ROADMAP.md Phase 213 Success Criteria: -->
<!-- SC#1 (`auth/visibility.py` deleted; all 23 inbound imports + 8 deferred-import call sites resolve to `catalog/authorization.py`):
       -> commands 4 (no old imports remain) + 5 (file deleted) + 7 (architecture guard catches future re-introduction) -->
<!-- SC#2 (RBAC-filtered search, tile, feature, STAC, OGC Records endpoints return identical results for the same user/role pairs):
       -> command 2 (full suite includes test_search.py + test_features.py + test_tiles.py + test_dataset_visibility.py + STAC/OGC tests) -->
<!-- SC#3 (1965-test backend baseline stays green, including visibility/authorization unit tests):
       -> command 2 (full suite at ≥1999 passing per RESEARCH.md A2 — the live count exceeds the baseline floor) -->
<!-- SC#4 (`git grep "auth.visibility|from app.modules.auth.visibility"` returns zero matches across the whole repo):
       -> command 6 (broader grep with pathspec exclusion of the test file itself) -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 04-01: Run phase verification gate and capture evidence to SUMMARY</name>
  <files>.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md</files>
  <read_first>
    - .planning/phases/213-catalog-authz-relocate/213-VALIDATION.md (Sampling Rate / Phase gate; Per-Task Verification Map rows 213-04-01, 213-04-02, 213-04-03)
    - .planning/phases/213-catalog-authz-relocate/213-RESEARCH.md ("Verification commands" section; Pitfall 4 — `alembic check` false alarm from pre-existing procrastinate / raw-SQL drift; Pitfall 5 — architecture tests SKIP inside container)
    - .planning/ROADMAP.md (Phase 213 Success Criteria — 4 conditions to satisfy)
    - .planning/phases/213-catalog-authz-relocate/213-CONTEXT.md (D-10 alembic; D-11 full pytest; D-12 RBAC parity proven by existing corpus; D-13 frontend untouched)
    - .planning/phases/212-core-settings-decouple/212-04-SUMMARY.md (the template — read end-to-end so this SUMMARY mirrors its structure 1:1 with only SC list and grep targets swapped)
    - .planning/phases/213-catalog-authz-relocate/213-01-SUMMARY.md (confirm Plan 01 produced the new file)
    - .planning/phases/213-catalog-authz-relocate/213-02-SUMMARY.md (confirm Plan 02 migrated callers, deleted the old file, and reports the pytest count)
    - .planning/phases/213-catalog-authz-relocate/213-03-SUMMARY.md (confirm Plan 03 added 2 new arch tests, total now 4)
  </read_first>
  <action>
Run each verification command in order. Capture the exit code and a brief excerpt of stdout/stderr. If ANY command exits non-zero, STOP and fix-forward in the appropriate plan; do not paper over a failure.

**Step 1 — Alembic schema-drift check (D-10, ROADMAP SC#1+SC#3 supporting evidence):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run alembic check
```

Expected: exit 0, output includes "No new upgrade operations." (or alembic 1.13's equivalent zero-diff message).

Per RESEARCH.md Pitfall 4, alembic may report drift from PRE-EXISTING items unrelated to Phase 213: procrastinate library tables and raw-SQL indexes are not in `Base.metadata`, so alembic always reports them as "pending." This drift predates Phase 212 and Phase 213. Reviewing the output:
- If drift mentions ONLY procrastinate tables (`procrastinate_*`), raw-SQL index names, or other items documented in `212-04-SUMMARY.md` — that is acceptable, expected pre-existing drift. The relocation did not introduce it.
- If drift mentions any of `app_settings`, `catalog.users`, `catalog.dataset_grants`, `catalog.records`, `catalog.datasets`, or any other catalog-domain table — STOP. Plan 01 or Plan 02 accidentally touched a `__tablename__`/`__table_args__` somewhere. Use `git show` of the deleted `auth/visibility.py` to confirm the relocation did not alter ORM identity.

If `alembic check` exits with `ModuleNotFoundError: app.modules.auth.visibility`, that means some module imported at alembic startup still references the deleted path — but RESEARCH.md "No alembic env.py caller" verified this is unexpected. Check `backend/alembic/env.py` for any new references and fix forward.

**Step 2 — Full backend test suite (D-11, ROADMAP SC#2+SC#3):**

```bash
docker compose exec api uv run pytest -m 'not perf' --tb=short -q 2>&1 | tee /tmp/213-04-pytest.log
```

If `docker compose` is not available, fall back to host-side: `cd backend && uv run pytest -m 'not perf' --tb=short -q`. The container path is preferred for live PostgreSQL/PostGIS test database connectivity. Note that the architecture-guard tests in `test_layering.py` will SKIP inside the container (Pitfall 5 — `.git/` excluded by `.dockerignore`); that is correct behavior. The host-only Step 7 below explicitly runs the architecture tests against `.git/`.

Expected: exit 0, summary line shows `≥1999 passed` (RESEARCH.md A2 floor). Plan 03 added 2 new architecture tests; inside the container those 2 plus the 2 Phase 212 arch tests SKIP (Pitfall 5), so the container-run summary line is `≥1999 passed, 4 skipped`. Capture the EXACT summary line in the SUMMARY.

If any test fails, classify by failure mode:
- `ModuleNotFoundError: app.modules.auth.visibility` → Plan 02 missed an importer (re-run Plan 02's grep gate).
- `ImportError: cannot import name 'X' from 'app.modules.catalog.authorization'` → Plan 01's public surface is malformed.
- `ModuleNotFoundError: app.modules.catalog.authorization` → Plan 01 was not committed.
- Test collection error in `test_layering.py` → Plan 03's path math or syntax is wrong.
- Genuine test failure (assertion, fixture, behavior change) → real RBAC regression introduced by the relocation. Compare `git show HEAD~N:backend/app/modules/auth/visibility.py` (where N walks back to before Plan 02's deletion) to `backend/app/modules/catalog/authorization.py` and find the diff.

**Step 3 — Ruff lint and format check:**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run ruff check .
cd /Users/ishiland/Code/geolens/backend && uv run ruff format --check .
```

Both must exit 0. Ruff catches F401 (unused imports) and F821 (unresolved imports). Plan 01's new file already passed ruff in Plan 01 verification; Plans 02 and 03 added/modified files that must pass cleanly here as the phase-level confirmation.

**Step 4 — ROADMAP SC#1 import-line gate:**

```bash
cd /Users/ishiland/Code/geolens
git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/ ; test $? -eq 1
```

The `test $? -eq 1` idiom inverts `git grep`'s "no-match-is-failure" exit-1 into "no-match-is-success-exit-0" for the gate. Expected: exit 0 (zero matches; ROADMAP SC#1's "all 15 direct visibility imports and 8 deferred-import call sites resolve to `catalog/authorization.py`" is satisfied).

**Step 5 — ROADMAP SC#1 file-deletion gate:**

```bash
test ! -e backend/app/modules/auth/visibility.py
```

Expected: exit 0 (file does not exist; ROADMAP SC#1's "`backend/app/modules/auth/visibility.py` is deleted" is satisfied).

**Step 6 — ROADMAP SC#4 broader reference gate:**

```bash
cd /Users/ishiland/Code/geolens
git grep -nE "auth\.visibility|from app\.modules\.auth\.visibility" -- backend/ ':!backend/tests/test_layering.py' ; test $? -eq 1
```

Expected: exit 0 (zero matches; ROADMAP SC#4's `git grep "auth.visibility|from app.modules.auth.visibility"` returns zero matches across the whole repo). The pathspec exclusion `:!backend/tests/test_layering.py` removes the test file's own regex literals from the match set — that is the same pattern Plan 03's `test_no_auth_visibility_module_referenced` test uses internally.

If Step 6 exits non-zero (matches found), examine each match:
- A non-import reference Plan 02 missed (e.g., a comment, docstring, or string literal mentioning `auth.visibility`) — fix it forward.
- A new file added by a concurrent quick-task between Plan 02's grep and Plan 04's gate — investigate the file, migrate any reference if appropriate.

**Step 7 — Architecture guard standalone (host-only; includes `.git/`):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
```

Expected: exit 0, "4 passed". This runs all four architecture tests (2 Phase 212 + 2 Phase 213). On the host, `.git/` is present so the tests do NOT skip; they execute the `git grep` subprocess against the working tree.

Note: Step 2 also ran these tests as part of the full suite, BUT inside the container they SKIP (Pitfall 5). Step 7 is the host-only confirmation that the guard tests actually ran and asserted the invariants.

If a test FAILS at this stage but Steps 4 / 6 PASSED, the test logic itself has a bug (path math, regex, pathspec). Re-read Plan 03 and the test bodies to find the discrepancy.

**Step 8 — Frontend-untouched gate (D-13):**

```bash
cd /Users/ishiland/Code/geolens
git diff --name-only $(git merge-base HEAD origin/main 2>/dev/null || git rev-parse HEAD~4)..HEAD -- frontend/
```

Expected: zero output (no frontend files modified across all commits since the phase started). The fallback `HEAD~4` covers the commits this phase produced. If output is non-empty, that is a Phase 213 scope violation — D-13 explicitly says "no frontend involvement." Investigate the file and either revert it or document why it was unavoidable.

**Step 9 — Capture evidence to SUMMARY.**

Create `.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md` with the following structure (substitute real values; mirror Phase 212-04-SUMMARY.md formatting 1:1):

````markdown
# Phase 213 - Plan 04 Verification Gate Evidence

**Run date:** {ISO timestamp}
**Result:** PASS / FAIL

## Verification Commands

| # | Command | Exit | Key output |
|---|---------|------|------------|
| 1 | `cd backend && uv run alembic check` | 0 | "No new upgrade operations." (or pre-existing procrastinate-only drift documented in 212-04-SUMMARY.md) |
| 2 | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | 0 | "{N} passed, {M} skipped in {T}s" — N≥1999, M includes the 4 architecture tests skipped inside container |
| 3a | `cd backend && uv run ruff check .` | 0 | "All checks passed!" |
| 3b | `cd backend && uv run ruff format --check .` | 0 | "{N} files already formatted" |
| 4 | `git grep -nE "^\s*(from\|import)\s+app\.modules\.auth\.visibility" -- backend/` | 1 (no matches) | (empty) |
| 5 | `test ! -e backend/app/modules/auth/visibility.py` | 0 | (file does not exist) |
| 6 | `git grep -nE "auth\.visibility\|from app\.modules\.auth\.visibility" -- backend/ ':!backend/tests/test_layering.py'` | 1 (no matches) | (empty) |
| 7 | `cd backend && uv run pytest tests/test_layering.py -v -m architecture` | 0 | "4 passed" (host-run; `.git/` present) |
| 8 | `git diff --name-only ... -- frontend/` | 0 (zero output) | (no frontend files modified) |

## ROADMAP Phase 213 Success Criteria - Status

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `backend/app/modules/auth/visibility.py` is deleted; all 15 direct visibility imports and 8 deferred-import call sites resolve to `catalog/authorization.py` | PASS | Steps 4 + 5 (zero old-path imports + file deleted) |
| 2 | RBAC-filtered search, tile, feature, STAC, and OGC Records endpoints return identical results for the same user/role pairs as before the relocation | PASS | Step 2 (full suite includes test_search.py + test_features.py + test_tiles.py + test_dataset_visibility.py + STAC/OGC integration tests; all pass at ≥1999 total) |
| 3 | The 1965-test backend baseline stays green, including the visibility/authorization unit tests | PASS | Step 2 (≥1999 passed; RESEARCH.md A2 floor exceeded) |
| 4 | `git grep "auth.visibility\|from app.modules.auth.visibility"` returns zero matches across the whole repo | PASS | Step 6 (broader grep with `:!backend/tests/test_layering.py` pathspec exclusion returns zero) + Step 7 (architecture-guard test 2 asserts same invariant) |

## Manual-Only Verifications

VALIDATION.md "Manual-Only Verifications" reports zero items: "All phase behaviors have automated verification. The phase deliberately adds no new RBAC behavior; existing test coverage proves parity." No reviewer step is required for Phase 213.

## Notes

- pyright/mypy NOT run because the project does not include a static type checker in its dev dependencies (verified `backend/pyproject.toml` `[dependency-groups].dev`); ruff (Step 3) is the canonical static check. Same as Phase 212-04.
- The architecture guard test scope now covers BOTH Phase 212 LAYER-01 (`from app.modules.settings`) AND Phase 213 LAYER-02 (`auth.visibility` import + broader reference). Phase 218 will broaden further per `test_layering.py` docstring.
- Pitfall 5 noted: the 4 architecture tests SKIP inside the container (Step 2) and PASS on the host (Step 7) — designed-in fallback behavior, not a regression.
- Pitfall 4 noted: any procrastinate / raw-SQL drift reported by Step 1 is pre-existing (documented in 212-04-SUMMARY.md) and unrelated to Phase 213. The relocation is pure-Python; no catalog-domain table changed.
- The `auth → catalog` cycle smell flagged in audit §5 is removed: Plan 01 promoted the `DatasetGrant` import from a function-scope deferred import to a module-level import, which is now legal because the file lives inside `catalog/`.
````

**Hard constraints:**

- This plan modifies ZERO source files. The only artifact is the SUMMARY at `.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md`.
- If any verification command exits non-zero, stop and fix-forward (in Plan 01, 02, or 03 as appropriate). Do NOT mark this plan PASS with a failure carried over.
- Do NOT skip Step 7 (host-only architecture run) just because Step 2 includes the same tests — Step 2's container run SKIPs them, so Step 7 is the only place they actually execute.
- Do NOT skip Step 8 (frontend-untouched check) — D-13 is explicit and verifiable.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && (cd backend && uv run alembic check) && (cd backend && uv run ruff check .) && (cd backend && uv run ruff format --check .) && bash -c 'git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/; test $? -eq 1' && test ! -e backend/app/modules/auth/visibility.py && bash -c 'git grep -nE "auth\.visibility|from app\.modules\.auth\.visibility" -- backend/ ":!backend/tests/test_layering.py"; test $? -eq 1' && (cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short -q) && bash -c '(docker compose exec api uv run pytest -m "not perf" --tb=short -q 2>&1 || cd backend && uv run pytest -m "not perf" --tb=short -q 2>&1) | tee /tmp/213-04-pytest.log | tail -5 | grep -E "[0-9]+ passed"' && test -f .planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md && grep -q "Result.*PASS" .planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md</automated>
  </verify>
  <acceptance_criteria>
    - `cd backend && uv run alembic check` exits 0 with no NEW catalog-domain schema diff (procrastinate / raw-SQL pre-existing drift documented in 212-04-SUMMARY.md is acceptable).
    - The full pytest invocation (`docker compose exec api uv run pytest -m 'not perf' --tb=short -q` OR host-fallback) exits 0; final summary line shows `≥1999 passed`. Capture the exact summary line in the SUMMARY.
    - `cd backend && uv run ruff check .` exits 0.
    - `cd backend && uv run ruff format --check .` exits 0.
    - `git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` returns ZERO matches (exit 1; closes ROADMAP SC#1's import clause).
    - `test ! -e backend/app/modules/auth/visibility.py` exits 0 (closes ROADMAP SC#1's deletion clause).
    - `git grep -nE "auth\.visibility|from app\.modules\.auth\.visibility" -- backend/ ':!backend/tests/test_layering.py'` returns ZERO matches (exit 1; closes ROADMAP SC#4).
    - `cd backend && uv run pytest tests/test_layering.py -v -m architecture` exits 0 with `4 passed` (host-run; on a container without `.git/`, it would report `4 skipped` — acceptable per Pitfall 5).
    - `git diff --name-only $(git merge-base HEAD origin/main)..HEAD -- frontend/` produces zero output (D-13).
    - `.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md` exists with the structured evidence table and a `**Result:** PASS` line.
    - The SUMMARY explicitly maps each ROADMAP SC#1–#4 to the verification command(s) that satisfied it (the "ROADMAP Phase 213 Success Criteria - Status" table).
  </acceptance_criteria>
  <done>
    All four ROADMAP Phase 213 success criteria are demonstrably met. The SUMMARY captures exit codes and key output for each command. Phase 213 is ready for `/gsd-verify-work` and ultimately for Phase 218's `/oc-audit` re-run to confirm the Boundary grade improvement (B → A−).
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
| T-213-11 | T (Tampering) — false-pass gate | The verification gate itself | mitigate | Each verification command is independently verifiable (`alembic check` against the live DB, full pytest run, ruff against the source tree, `git grep` against the working tree). The SUMMARY reports exit codes and stdout excerpts that can be re-run by Phase 218 or any reviewer. The combined gate covers ROADMAP SC#1-#4 with explicit 1:1 mapping (see `<interfaces>` block). |
| T-213-12 | E (Elevation via skipping the gate) | Phase exit | accept | If a contributor merges without running this plan, `/gsd-verify-work` will catch the missing SUMMARY artifact and Phase 218's audit re-run will catch any reintroduced finding. The plan is the proof, not the policy. |
| T-213-13 | INFO — no new external surface | (none) | accept | This plan modifies no production files. |
</threat_model>

<verification>
- ROADMAP SC#1 verified by Step 4 (zero `auth.visibility` import-shaped lines under `backend/`) AND Step 5 (file deleted).
- ROADMAP SC#2 verified by `test_search.py`, `test_features.py`, `test_tiles.py`, `test_dataset_visibility.py`, plus the STAC and OGC Records integration tests passing within the full suite (Step 2).
- ROADMAP SC#3 verified by ≥1999 tests passing in the full suite (Step 2 — exceeds the 1965 baseline floor in CONTEXT.md D-11; RESEARCH.md A2 confirms the live count).
- ROADMAP SC#4 verified by Step 6 (broader `auth.visibility` grep with pathspec exclusion returns zero matches) AND Step 7 (architecture-guard test 2 asserts the same invariant from inside the test suite).
- D-10: No migration generated — verified by Step 1 exit 0 with no NEW catalog-domain schema diff.
- D-11: Baseline holds — verified by Step 2 (≥1999 passed).
- D-12: RBAC parity — verified by Step 2 (full corpus across search/tile/feature/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox).
- D-13: No frontend work — verified by Step 8 (zero entries under `frontend/` in the phase diff).
</verification>

<success_criteria>
- All four ROADMAP Phase 213 success criteria are demonstrably met with command-level evidence in `.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md`.
- Phase 213 is ready for orchestrator-level `/gsd-verify-work` and for Phase 218's `/oc-audit` re-run.
- The phase introduced zero behavior change at the wire level (HTTP contract unchanged, DB schema unchanged) — only the Python module path of dataset visibility helpers and an extension of the architecture guard test.
- The audit's §5 finding ("`auth/visibility.py:148` does `from app.modules.catalog.datasets.domain.models import DatasetGrant` (deferred import to break a cycle)") no longer reproduces — Plan 01 promoted the import to module level, and Plan 02 deleted the source file.
</success_criteria>

<output>
After completion, the SUMMARY at `.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md` is the artifact. It must contain:
- A `**Result:** PASS` (or `FAIL` with diagnostic notes) header.
- The structured evidence table mapping each verification command (Steps 1-8) to its exit code and a one-line stdout excerpt.
- The ROADMAP Phase 213 SC#1-SC#4 status table with PASS/FAIL and evidence pointers.
- A note that pyright was not run because it is not a project dev dependency (ruff is the canonical static check).
- A note that the architecture-guard skip behavior in container is by design (Pitfall 5).
- A note that any procrastinate / raw-SQL drift in Step 1 is pre-existing (Pitfall 4), not introduced by Phase 213.
</output>
</content>
</invoke>