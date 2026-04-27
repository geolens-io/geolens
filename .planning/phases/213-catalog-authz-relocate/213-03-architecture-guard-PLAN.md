---
phase: 213-catalog-authz-relocate
plan: 03
type: execute
wave: 3
depends_on: ["213-02"]
files_modified:
  - backend/tests/test_layering.py
autonomous: true
requirements: [LAYER-02]
requirements_addressed: [LAYER-02]
tags: [test, architecture, layering, ci, open-core]

must_haves:
  truths:
    - "D-07: `backend/tests/test_layering.py` is extended with TWO new `@pytest.mark.architecture` tests: `test_no_imports_from_auth_visibility` (import-shaped grep across `backend/`) and `test_no_auth_visibility_module_referenced` (broader grep across `backend/` with pathspec exclusion `:!backend/tests/test_layering.py` to avoid the self-positive bug from Phase 212-03 commit b0bd0c2c)."
    - "D-08: Both new tests reuse the existing `_has_git_metadata()` skip guard and (where compatible) the `_git_grep` helper from the existing file. Test 2 calls `subprocess.run` directly because it needs the pathspec-exclude argument that `_git_grep` does not support."
    - "D-09: The module docstring at the top of `test_layering.py` is updated to document the broadened scope — was 'Phase 212 LAYER-01 only', now 'Phases 212 LAYER-01 + 213 LAYER-02'. The Phase 214 / Phase 218 forward-note is preserved."
    - "The new tests pass against the post-Plan 02 codebase (because Plan 02 already removed every matching import). Both tests run by default in CI (no `addopts` change needed) and can be opt-out locally via `pytest -m 'not architecture'`."
    - "The `architecture` marker is already registered in `backend/pyproject.toml` (Phase 212-03); no marker change is needed."
    - "If a future contributor reintroduces an `app.modules.auth.visibility` import or any `auth.visibility` reference outside `test_layering.py`, the corresponding test fails immediately with a clear message naming the offending lines."
  artifacts:
    - path: "backend/tests/test_layering.py"
      provides: "Architecture guard test extended with two new tests covering Phase 213 LAYER-02"
      contains: "test_no_imports_from_auth_visibility"
      min_lines: 130
  key_links:
    - from: "backend/tests/test_layering.py"
      to: "backend/"
      via: "subprocess.run + git grep (test 2 uses pathspec exclusion `:!backend/tests/test_layering.py`)"
      pattern: ":!backend/tests/test_layering.py"
---

<objective>
Extend `backend/tests/test_layering.py` with two new `@pytest.mark.architecture` tests that prevent re-introduction of `app.modules.auth.visibility` references after Plan 02 deletes the module:

1. `test_no_imports_from_auth_visibility` — anchored regex `^\s*(from|import)\s+app\.modules\.auth\.visibility` across `backend/`, exit code 0 = fail with offending lines. Maps to ROADMAP SC#4. Reuses the existing `_git_grep` helper.
2. `test_no_auth_visibility_module_referenced` — broader unrestricted regex `app\.modules\.auth\.visibility|auth\.visibility` across `backend/` with pathspec exclusion `:!backend/tests/test_layering.py` to prevent the regex literals inside the test file itself from matching (the self-positive bug fixed by Phase 212-03 commit `b0bd0c2c`). This catches re-export shims in `__init__.py` files that the import-anchor in test 1 would miss. Calls `subprocess.run` directly because `_git_grep` does not support pathspec arguments.

Update the module-level docstring to broaden the scope from "Phase 212 LAYER-01 only" to "Phases 212 LAYER-01 + 213 LAYER-02". The existing docstring already anticipates this expansion: it says "Phases 213 (catalog-authz-relocate) and 214 (identity-protocol-extract) close additional core->modules edges; Phase 218 will broaden this guard..." — update it to reflect that 213 has now landed.

Purpose: Phase 218 will re-run `/oc-audit` to verify Boundary grades improved from B to A−. Without an automated guard, the next contributor who adds `from app.modules.auth.visibility import X` (or a re-export shim) anywhere in the codebase will silently reintroduce the audit finding and Phase 218's audit re-run will fail. The guard is cheap (one process spawn per test, ~50 ms each) and explicit about the rule (D-07).

Output: ONE file modified (`backend/tests/test_layering.py`) — extended with two new test functions, plus a docstring update. The `architecture` marker is already registered in `pyproject.toml` from Phase 212-03; no `pyproject.toml` change is needed. The two tests pass on the post-Plan 02 codebase and would FAIL if `auth.visibility` references were reintroduced.
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
@.planning/phases/213-catalog-authz-relocate/213-PATTERNS.md
@.planning/phases/213-catalog-authz-relocate/213-VALIDATION.md
@.planning/phases/213-catalog-authz-relocate/213-01-SUMMARY.md
@.planning/phases/213-catalog-authz-relocate/213-02-SUMMARY.md
@backend/tests/test_layering.py
@backend/pyproject.toml

<interfaces>
<!-- Existing test_layering.py structure (verified by reading the live file 2026-04-27): -->

```
Lines 1-16:  Module docstring (CURRENT scope: "Phase 212 LAYER-01 only")
Line 18:     from __future__ import annotations
Line 20:     import subprocess
Line 21:     from pathlib import Path
Line 23:     import pytest
Line 26:     REPO_ROOT = Path(__file__).resolve().parents[2]   # backend/tests -> backend -> repo root
Lines 29-36: def _has_git_metadata() -> bool:        (existing skip-guard helper)
Lines 39-46: def _git_grep(pattern, path) -> CompletedProcess:  (existing reusable helper)
Lines 49-76: @pytest.mark.architecture
             def test_core_does_not_import_from_settings_module()   (Phase 212 LAYER-01 — uses _git_grep)
Lines 79-106: @pytest.mark.architecture
              def test_app_settings_imports_only_via_core_db_models()  (Phase 212 LAYER-01 — uses _git_grep with import-anchor)
```

The existing `_git_grep` helper signature (lines 39-46):
```python
def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
```

This helper takes `pattern` and a single `path` argument. It does NOT accept additional pathspec arguments like `:!backend/tests/test_layering.py`. Test 1 uses `_git_grep` (single path is fine). Test 2 calls `subprocess.run` directly because it needs to pass the extra pathspec argument.

CURRENT module docstring text (lines 1-16; the lines to edit are lines 8-11):
```
"""Layering rules: core/ must not depend on modules/settings/.

Enforces the open-core boundary closed by Phase 212. If this test fails, a
`from app.modules.settings.<...>` import (or `import app.modules.settings.<...>`)
was introduced under `backend/app/core/`, which violates the rule that modules
depend on core, not the reverse.

Scope (Phase 212): NARROW — only `from app.modules.settings`. Phases 213
(catalog-authz-relocate) and 214 (identity-protocol-extract) close additional
core->modules edges; Phase 218 will broaden this guard to `from app.modules.<*>`
once those phases land.

Markers:
- `@pytest.mark.architecture` — opt-out locally with `pytest -m 'not architecture'`
  (D-07). Runs by default in CI because `addopts` does not exclude it.
"""
```

Per RESEARCH.md "Open Question 2", the docstring update is minimal: change "Scope (Phase 212): NARROW — only `from app.modules.settings`" to "Scope (Phases 212–213): `from app.modules.settings` (Phase 212 LAYER-01) and `from app.modules.auth.visibility` (Phase 213 LAYER-02)". Preserve the Phase 214 / Phase 218 forward note (the existing sentence "Phase 218 will broaden this guard to `from app.modules.<*>` once those phases land" stays, though "Phases 213 ... close additional core->modules edges" becomes "Phase 214 closes additional core->modules edges" since 213 has now landed).

The pyproject.toml `architecture` marker is already registered (Phase 212-03 added it):
```toml
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
    "architecture: layering and boundary tests; opt-out locally with `-m 'not architecture'` (Phase 212 LAYER-01 guard)",
]
```

This marker registration is reused as-is. **DO NOT modify `backend/pyproject.toml`.**
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 03-01: Extend test_layering.py with two new architecture guard tests + update docstring</name>
  <files>backend/tests/test_layering.py</files>
  <read_first>
    - backend/tests/test_layering.py (read end-to-end — current 107 lines; understand the `_has_git_metadata()` helper at lines 29-36, `_git_grep` helper at lines 39-46, and the two existing tests at lines 49-76 and 79-106 as templates for the two new tests)
    - backend/pyproject.toml (verify `architecture` marker is registered — search for `architecture: layering` in the `[tool.pytest.ini_options].markers` list; confirm `addopts = "-m 'not perf'"` is present and does NOT exclude `architecture`; DO NOT modify this file)
    - .planning/phases/213-catalog-authz-relocate/213-CONTEXT.md (D-07 — extend existing file with two new tests; D-08 — reuse `_has_git_metadata` and `_git_grep`; D-09 — docstring update)
    - .planning/phases/213-catalog-authz-relocate/213-RESEARCH.md ("Pattern 5" — full code template for both new tests; Pitfall 3 — self-positive bug from Phase 212-03 commit b0bd0c2c, fixed via pathspec exclusion `:!backend/tests/test_layering.py`; Pitfall 5 — `.git/` is absent inside the API container, so `_has_git_metadata()` returns False and the tests SKIP — designed-in fallback)
    - .planning/phases/213-catalog-authz-relocate/213-PATTERNS.md ("test_layering.py" pattern assignment — the exact code blocks to insert and the docstring diff)
    - .planning/phases/213-catalog-authz-relocate/213-VALIDATION.md (Per-Task Verification Map rows 213-03-01 and 213-03-02)
  </read_first>
  <action>
**Step 1 — Update the module docstring** (lines 1-16 of `backend/tests/test_layering.py`).

Replace the existing docstring with the version below. The changes are:
- Line 1 title broadened from "Layering rules: core/ must not depend on modules/settings/." to "Layering rules: core/ must not depend on modules/settings/, and modules/auth/visibility.py is gone."
- Line 3 ("Enforces the open-core boundary closed by Phase 212.") broadened to mention both phases.
- The "Scope" paragraph rewritten per RESEARCH.md Open Question 2.
- The Markers paragraph kept verbatim.

Use the Edit tool with `old_string` set to the EXACT current 16-line docstring (lines 1-16 inclusive of the closing `"""`) and `new_string` set to:

```python
"""Layering rules: core/ must not depend on modules/settings/, and modules/auth/visibility.py is gone.

Enforces open-core boundaries closed by Phases 212 and 213. If a test in this
file fails, a forbidden import (`from app.modules.settings.<...>` under
`backend/app/core/`, OR `from app.modules.auth.visibility import ...` anywhere
under `backend/`) was reintroduced, which violates the layering rules that
modules depend on core (not the reverse) and that catalog authorization lives
in `app.modules.catalog.authorization` (not `app.modules.auth.visibility`).

Scope (Phases 212-213):
- `from app.modules.settings` under `backend/app/core/` (Phase 212 LAYER-01)
- `from app.modules.auth.visibility` anywhere under `backend/` (Phase 213 LAYER-02)
- Broader `auth.visibility` reference catch (Phase 213 LAYER-02; pathspec excludes this test file to avoid the self-positive bug from Phase 212-03 commit b0bd0c2c)

Phase 214 (identity-protocol-extract) closes additional core->modules edges;
Phase 218 will broaden this guard to `from app.modules.<*>` once those phases land.

Markers:
- `@pytest.mark.architecture` - opt-out locally with `pytest -m 'not architecture'`
  (D-07). Runs by default in CI because `addopts` does not exclude it.
"""
```

(Note: the doublequotes are ASCII; do NOT use Unicode em-dashes — keep ASCII hyphens for shell/grep compatibility. The forward-note preserves the Phase 214 / Phase 218 reference per RESEARCH.md Open Question 2.)

**Step 2 — Append two new tests at the end of the file** (after the existing `test_app_settings_imports_only_via_core_db_models` function, which ends at line 106 of the current file).

Use the Edit tool with `old_string` set to the closing few lines of the existing test 2 (e.g., the last 3-4 lines including the trailing newline) and `new_string` set to those same lines PLUS the two new test functions appended. Or use the Write tool only if you have just read the entire file in this task (per the no-heredoc rule); if reading + appending via Edit is cleaner, do that.

The two new tests to append (verbatim):

```python


@pytest.mark.architecture
def test_no_imports_from_auth_visibility() -> None:
    """`auth.visibility` import path must not appear anywhere under `backend/`.

    Closes Phase 213 LAYER-02: the deleted `app.modules.auth.visibility` path
    becomes a hard ModuleNotFoundError after this phase - any surviving import
    is a migration miss. Maps directly to ROADMAP SC#4.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.auth\.visibility",
        "backend/",
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: deleted import path `app.modules.auth.visibility` is still "
            "referenced. Migrate to `app.modules.catalog.authorization`. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_auth_visibility_module_referenced() -> None:
    """Broader guard: `auth.visibility` string must not appear as a module reference.

    Catches re-exports in `__init__.py` files or indirect references that the
    import-shaped guard above would miss. Excludes this test file itself via
    a `:!` pathspec so the regex literal in the guard does not produce a
    self-positive (Phase 212-03 bug, commit b0bd0c2c — fixed there with an
    import-anchor; here we use the broader regex deliberately and rely on the
    pathspec exclusion instead).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"app\.modules\.auth\.visibility|auth\.visibility",
            "--",
            "backend/",
            ":!backend/tests/test_layering.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: `auth.visibility` is referenced outside test_layering.py. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**Step 3 — Verify the additions parse and pass:**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
```

Expected: 4 passed (the 2 existing Phase 212 tests + the 2 new Phase 213 tests). If a test FAILS:
- `test_no_imports_from_auth_visibility` failing → Plan 02 missed a caller. Re-run `git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` to find the orphan and fix it.
- `test_no_auth_visibility_module_referenced` failing → either Plan 02 missed a non-import reference (e.g., a comment or docstring mentioning `auth.visibility`), OR the pathspec exclusion `:!backend/tests/test_layering.py` is not working in the local git version. If the failure output names lines from `test_layering.py` itself, the pathspec is being ignored — check git version (`git --version` should be ≥2.13, where `:!` pathspec was introduced; the project uses modern git).

If the pathspec exclusion fundamentally does not work (very unlikely but possible in some constrained environments), fall back to the import-anchor pattern proven in Phase 212-03 commit `b0bd0c2c`: change the regex in test 2 from `r"app\.modules\.auth\.visibility|auth\.visibility"` to `r"^\s*(from|import)\s+app\.modules\.auth\.visibility"` and remove the pathspec argument. This makes test 2 redundant with test 1; document the fallback in the SUMMARY. (This fallback is RESEARCH.md "Open Questions" item 1's recommendation if option (a) — pathspec — fails.)

Also verify the marker registration silenced any `PytestUnknownMarkWarning`:

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v 2>&1 | grep -c "PytestUnknownMarkWarning" | tr -d ' '
```

Expected: 0 (the marker is already registered from Phase 212-03; no new registration needed).

**Step 4 — Negative-test discipline (manual; document only, do NOT commit the violation):**

As a one-time confidence check, temporarily edit `backend/app/modules/auth/dependencies.py` to add the line `from app.modules.auth.visibility import get_user_roles  # NEGATIVE TEST` near the other imports, run `cd backend && uv run pytest tests/test_layering.py::test_no_imports_from_auth_visibility -v` and confirm it FAILS with a clear "Regression: deleted import path" message naming `dependencies.py`. Then `git checkout backend/app/modules/auth/dependencies.py` to revert. Document the result (pass-on-revert, fail-on-introduction) in the plan SUMMARY. DO NOT commit the violation.

For test 2, do the same with `backend/app/modules/auth/__init__.py`: temporarily change the docstring to reference `auth.visibility` (e.g., `"""Auth module namespace. See app.modules.auth.visibility (deprecated, Phase 213)."""`), run `cd backend && uv run pytest tests/test_layering.py::test_no_auth_visibility_module_referenced -v`, confirm it FAILS naming `__init__.py`, then `git checkout` to revert. This proves the broader test catches non-import references.

**Hard constraints:**

- DO NOT modify `backend/pyproject.toml`. The `architecture` marker is already registered.
- DO NOT modify `backend/pyproject.toml`'s `addopts`. `pytest -m 'not perf'` is the default; `architecture` tests must run by default in CI.
- DO NOT touch the existing two tests (`test_core_does_not_import_from_settings_module`, `test_app_settings_imports_only_via_core_db_models`) — they are correct as-is.
- DO NOT change the `_has_git_metadata()` or `_git_grep` helpers — they are reused by the new tests (test 1 uses `_git_grep`; test 2 uses `subprocess.run` directly because of the pathspec).
- DO NOT change `REPO_ROOT = Path(__file__).resolve().parents[2]` — the path math is correct (test file at `backend/tests/test_layering.py` → parents[0]=tests, parents[1]=backend, parents[2]=repo root).
- The new tests' regex strings MUST use raw-string literals (`r"..."`) to avoid double-escaping backslashes (Python string + regex). Both new test bodies above already use `r"..."`.
- After this plan, `cd backend && uv run pytest tests/test_layering.py -v -m architecture` reports `4 passed` (or `4 skipped` if run inside a container without `.git/`; per Pitfall 5, both are acceptable behaviors).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && grep -q "test_no_imports_from_auth_visibility" backend/tests/test_layering.py && grep -q "test_no_auth_visibility_module_referenced" backend/tests/test_layering.py && grep -q ":!backend/tests/test_layering.py" backend/tests/test_layering.py && grep -q "Scope (Phases 212-213)" backend/tests/test_layering.py && (cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short -q) && (cd backend && uv run pytest tests/test_layering.py -v 2>&1 | grep -c "PytestUnknownMarkWarning" | tr -d ' ' | (read n; test "$n" = "0"))</automated>
  </verify>
  <acceptance_criteria>
    - File `backend/tests/test_layering.py` contains a function named `test_no_imports_from_auth_visibility` decorated with `@pytest.mark.architecture` (verifiable via `grep -E "^def test_no_imports_from_auth_visibility|^@pytest.mark.architecture$" backend/tests/test_layering.py`).
    - File contains a function named `test_no_auth_visibility_module_referenced` decorated with `@pytest.mark.architecture`.
    - File contains the literal string `":!backend/tests/test_layering.py"` (the pathspec exclusion in test 2; verifiable via `grep -F ':!backend/tests/test_layering.py' backend/tests/test_layering.py` returning 1 match).
    - File contains the literal string `Scope (Phases 212-213)` in the module docstring (the docstring update; verifiable via `grep -F 'Scope (Phases 212-213)' backend/tests/test_layering.py` returning 1 match).
    - Both new tests call `pytest.skip("git metadata unavailable; arch test only runs on full clones")` when `_has_git_metadata()` returns False (Pitfall 5 / D-08).
    - `cd backend && uv run pytest tests/test_layering.py -v -m architecture` exits 0 with `4 passed` (2 Phase 212 tests + 2 new Phase 213 tests). On a host with `.git/` present, all 4 PASS; on a container without `.git/`, all 4 SKIP — both outcomes are acceptable per Pitfall 5.
    - `cd backend && uv run pytest tests/test_layering.py -v 2>&1 | grep -c "PytestUnknownMarkWarning"` returns 0 (the `architecture` marker is already registered from Phase 212-03; no new registration needed).
    - `git diff backend/pyproject.toml` produces zero output (DO NOT modify this file).
    - `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_settings_module -v` and `cd backend && uv run pytest tests/test_layering.py::test_app_settings_imports_only_via_core_db_models -v` BOTH still pass — the existing two Phase 212 tests are unchanged.
    - `grep -c "^def test_" backend/tests/test_layering.py` returns 4 (the two existing tests + the two new tests).
    - `grep -c "_git_grep" backend/tests/test_layering.py` returns ≥3 (the helper definition + the existing tests' calls + test 1's call). Test 2 uses `subprocess.run` directly so it does NOT add another `_git_grep` call.
  </acceptance_criteria>
  <done>
    `backend/tests/test_layering.py` is extended with the two new Phase 213 architecture guard tests; the module docstring reflects the broadened scope. All 4 architecture tests pass on the post-Plan 02 codebase. Future reintroduction of `auth.visibility` (whether as an import or as a re-export shim) will trigger an immediate, named test failure. `pyproject.toml` is unchanged (the `architecture` marker is already registered from Phase 212-03).
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

This plan adds CI guard tests. No new code paths are introduced into the production runtime; the test file is collected only by pytest and never imported by `app/`. The architecture-guard boundary (developer-vs-CI) was established by Phase 212-03 and is being extended, not redefined.

| Boundary | Description |
|----------|-------------|
| (none in app runtime) | Test-only addition; no impact on production trust boundaries. |
| Developer-vs-CI (existing from Phase 212-03) | The `architecture` marker provides a controlled opt-out for local TDD loops; the guard still runs in CI's default invocation. Phase 213 widens the scope of this boundary to include LAYER-02. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-213-08 | E (Elevation of Privilege) — guard bypass via pathspec evasion | `test_no_auth_visibility_module_referenced` (test 2) | mitigate | The pathspec `:!backend/tests/test_layering.py` is the ONLY exclusion; any other file containing `auth.visibility` triggers the failure. A contributor cannot smuggle a reference into another file because the broader regex catches docstrings, comments, and re-export shims in addition to import-shaped lines. The narrower test 1 uses an import-line anchor and catches actual imports. The two tests are complementary. |
| T-213-09 | T (Tampering) — guard self-positive | `test_no_auth_visibility_module_referenced` if pathspec is ignored | mitigate | The pathspec exclusion `:!backend/tests/test_layering.py` is supported by `git grep` ≥2.13, which the project uses (modern git). The fallback in the action's "Step 3" is the import-anchor pattern proven in Phase 212-03 commit `b0bd0c2c`. The negative-test discipline in Step 4 verifies the guard fires loudly when the violation is introduced and reverts cleanly. |
| T-213-10 | INFO — guard skips inside container | `_has_git_metadata()` skip | accept | RESEARCH.md Pitfall 5 documents this is by design: `.dockerignore` excludes `.git/` from the container image, so the architecture guard tests SKIP (not FAIL) when run via `docker compose exec api uv run pytest`. Phase 218 audits the host-run output. The skip path is a safety belt, not a primary control. |
</threat_model>

<verification>
- `cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short` exits 0 with `4 passed` (or `4 skipped` if run inside a container without `.git/`).
- `cd backend && uv run pytest tests/test_layering.py::test_no_imports_from_auth_visibility -v` exits 0 with PASS.
- `cd backend && uv run pytest tests/test_layering.py::test_no_auth_visibility_module_referenced -v` exits 0 with PASS.
- `cd backend && uv run pytest tests/test_layering.py -v` (no `-m`) ALSO exits 0 with all 4 architecture tests passing (architecture tests run by default per Phase 212-03's marker registration; `addopts` is unchanged).
- No `PytestUnknownMarkWarning` is emitted (`grep -c PytestUnknownMarkWarning` returns 0 from the pytest output).
- `git diff backend/pyproject.toml` produces zero output (NOT modified).
- The negative-test discipline (Step 4) confirms each new test FAILS when an actual violation is temporarily introduced and PASSES when reverted. Capture the failure messages in the SUMMARY.
- `grep -c "^def test_" backend/tests/test_layering.py` returns 4.
</verification>

<success_criteria>
- The audit's "auth.visibility" smell cannot silently re-emerge: any reintroduction of an `app.modules.auth.visibility` import or an `auth.visibility` reference outside `test_layering.py` triggers a clear, named test failure on the next pytest run.
- The guard is opt-out for local dev (D-07) but mandatory in default CI invocation (the `architecture` marker is registered and `addopts` does not exclude it).
- The narrow scope (test 1: import-shaped; test 2: broader with pathspec exclusion) avoids both false negatives (re-export shims) and false positives (the test file's own regex literals).
- The test_layering.py docstring documents the broadened Phase 212 + 213 scope.
</success_criteria>

<output>
After completion, create `.planning/phases/213-catalog-authz-relocate/213-03-SUMMARY.md` documenting:
- The two new test functions added and their pass/fail status against the post-Plan 02 codebase.
- The docstring diff (was "Scope (Phase 212): NARROW", now "Scope (Phases 212-213)" with explicit phase mapping).
- The negative-test discipline result (Step 4): pass-on-revert, fail-on-introduction. Include a snippet of each test's failure message to confirm the guard names the offending file/line.
- A note that the guard scope now covers BOTH `from app.modules.settings` (Phase 212 LAYER-01, narrow path) AND `app.modules.auth.visibility` (Phase 213 LAYER-02, narrow + broad paths). Phase 218 will broaden further.
- Confirmation that `backend/pyproject.toml` was NOT modified (the `architecture` marker is already registered from Phase 212-03).
- Whether the pathspec exclusion `:!backend/tests/test_layering.py` works in the project's git version, or whether the fallback (import-anchor in both tests) had to be applied. (Default expectation: pathspec works; document the fallback only if it was actually needed.)
</output>
</content>
</invoke>