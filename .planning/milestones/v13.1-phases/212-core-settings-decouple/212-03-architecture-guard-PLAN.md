---
phase: 212-core-settings-decouple
plan: 03
type: execute
wave: 3
depends_on: ["212-02"]
files_modified:
  - backend/tests/test_layering.py
  - backend/pyproject.toml
autonomous: true
requirements: [LAYER-01]
requirements_addressed: [LAYER-01]
tags: [test, architecture, layering, ci, open-core]

must_haves:
  truths:
    - "A pytest test under `backend/tests/test_layering.py` asserts that no file under `backend/app/core/` contains a `from app.modules.settings` import."
    - "The test is marked `@pytest.mark.architecture` so it can be opted-out locally with `pytest -m 'not architecture'` (D-07) but runs by default in CI (the default pytest collection includes it because no exclusion flag is set in `addopts`)."
    - "The test gracefully skips when `.git/` is unavailable (RESEARCH.md Pitfall 4 — `_has_git_metadata()` skip guard); it does not error inside containers that lack git metadata."
    - "If a future contributor reintroduces the layering inversion, the test fails immediately with a clear message naming the offending file."
    - "The `architecture` marker is registered in `backend/pyproject.toml` so `pytest -m architecture` and `pytest -m 'not architecture'` produce no `PytestUnknownMarkWarning`."
  artifacts:
    - path: "backend/tests/test_layering.py"
      provides: "Architecture guard test enforcing LAYER-01 boundary"
      contains: "test_core_does_not_import_from_settings_module"
      min_lines: 30
    - path: "backend/pyproject.toml"
      provides: "`architecture` marker registration for pytest"
      contains: "architecture: layering"
  key_links:
    - from: "backend/tests/test_layering.py"
      to: "backend/app/core/"
      via: "subprocess.run([\"git\", \"grep\", ...])"
      pattern: "subprocess\\.run.*git.*grep"
    - from: "backend/pyproject.toml"
      to: "backend/tests/test_layering.py"
      via: "pytest marker registration"
      pattern: "architecture:"
---

<objective>
Add a CI-runnable architecture guard test that prevents the LAYER-01 inversion from being silently reintroduced. The test shells out to `git grep` to assert that no file under `backend/app/core/` contains a `from app.modules.settings` import, and gracefully skips when `.git/` is unavailable (RESEARCH.md Pitfall 4). Register the `architecture` pytest marker in `backend/pyproject.toml` so the test can be opt-out locally (`pytest -m 'not architecture'`) per D-07.

Purpose: Phase 218 will re-run `/oc-audit` to verify Boundary grades improved from B to A−. Without an automated guard, the next contributor who adds `from app.modules.settings import AppSetting` (or anything else from that module) into `core/` will silently reopen the audit finding and Phase 218 will fail. The guard is cheap (one `git grep` subprocess in <100 ms) and explicit about the rule (D-06).

Output: Two files modified. `backend/tests/test_layering.py` is created (NEW) with the guard test; `backend/pyproject.toml` `[tool.pytest.ini_options].markers` list gets one new entry for the `architecture` marker. The test passes by default (because Plan 02 already removed all matching imports from core/) and would FAIL if the LAYER-01 inversion were reintroduced.

**Scope decision (per RESEARCH.md Open Question 1):** This phase implements the NARROW rule — `from app.modules.settings` only — not the broader `from app.modules.<anything>` rule. Reason: `core/persistent_config.py` still has two unrelated `from app.modules.*` imports (line 21 `from app.modules.audit.service import log_action`, line 638 `from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS`) which are scope for Phase 213 (catalog-authz) and Phase 214 (identity-protocol). A broader rule here would either fail immediately (breaking CI for unrelated reasons) or require a tolerated-exceptions list (which is bookkeeping debt). Phase 218 broadens the rule once 213/214 land. [VERIFIED 2026-04-27 by `git grep -n "from app\.modules" -- backend/app/core/`]
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
@.planning/phases/212-core-settings-decouple/212-02-SUMMARY.md
@backend/pyproject.toml

<interfaces>
<!-- Existing pyproject.toml markers section (verified 2026-04-27 at lines 75-78): -->

```toml
[tool.pytest.ini_options]
# ... anyio_mode, asyncio_mode, etc. ...
testpaths = ["tests"]
addopts = "-m 'not perf'"
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
]
```

<!-- We add a third entry to the `markers` list. -->
<!-- The `addopts = "-m 'not perf'"` line means pytest-by-default does NOT run perf tests. We do NOT add `not architecture` to addopts — the architecture guard MUST run by default in CI (D-07). Contributors can opt out locally with `pytest -m 'not architecture'`. -->

<!-- Pattern from RESEARCH.md "Architecture Patterns / Pattern 2" — recommended subprocess git grep + _has_git_metadata() skip guard: -->

```python
# Recommended structure (full template at RESEARCH.md Architecture Patterns / Pattern 2):
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests/test_layering.py -> repo root


def _has_git_metadata() -> bool:
    return (REPO_ROOT / ".git").exists()


@pytest.mark.architecture
def test_core_does_not_import_from_settings_module() -> None:
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    result = subprocess.run(
        ["git", "grep", "-n", "-E", r"^\s*(from|import)\s+app\.modules\.settings",
         "--", "backend/app/core/"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:  # 0 = matches found = violation
        pytest.fail("Layering violation: ... " + result.stdout)
    if result.returncode not in (0, 1):
        pytest.fail(f"git grep failed: rc={result.returncode}\n{result.stderr}")
```

<!-- Path math: `Path(__file__).resolve().parents[2]` yields the repo root because `__file__` is `<repo>/backend/tests/test_layering.py`; .parents[0]=tests, .parents[1]=backend, .parents[2]=<repo>. Verified by inspection. -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 03-01: Create backend/tests/test_layering.py and register `architecture` marker in pyproject.toml</name>
  <files>backend/tests/test_layering.py, backend/pyproject.toml</files>
  <read_first>
    - .planning/phases/212-core-settings-decouple/212-CONTEXT.md (D-06 — guard rule; D-07 — opt-out posture)
    - .planning/phases/212-core-settings-decouple/212-RESEARCH.md (Architecture Patterns / Pattern 2 — full code template; Pitfall 4 — `_has_git_metadata()` skip; Open Question 1 — narrow vs broad rule, narrow chosen)
    - backend/pyproject.toml (lines 67-80 — pytest config; the `markers` list is currently 2 entries at lines 75-78)
    - .planning/phases/212-core-settings-decouple/212-02-SUMMARY.md (confirms LAYER-01 imports are migrated; the new guard test should now PASS by default — if it fails, Plan 02 had a missed migration site)
  </read_first>
  <action>
**Step 1 — Create `backend/tests/test_layering.py` with two tests.**

Write the file with the exact content below. The tests use `subprocess.run(["git", "grep", ...])` (RESEARCH.md "Don't Hand-Roll" — git grep beats AST walkers for this scope; one process spawn, ~50 ms) and use the `_has_git_metadata()` skip pattern from RESEARCH.md Pitfall 4 to avoid breaking inside containers that lack `.git/`.

```python
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

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# backend/tests/test_layering.py -> backend/tests -> backend -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]


def _has_git_metadata() -> bool:
    """Return True if `.git/` is present at the repo root.

    Subprocess-based `git grep` requires git metadata. Some container test
    invocations may exclude `.git/` via `.dockerignore`; in that case we skip
    rather than fail (RESEARCH.md Pitfall 4).
    """
    return (REPO_ROOT / ".git").exists()


def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.architecture
def test_core_does_not_import_from_settings_module() -> None:
    """`backend/app/core/` must never import from `app.modules.settings`.

    Closes Phase 212 LAYER-01: the `core <-> settings` layering inversion at
    `core/persistent_config.py:30` and `core/public_urls.py:14` is gone, and
    must stay gone.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.settings",
        "backend/app/core/",
    )

    # git grep exit codes: 0 = matches found, 1 = no matches, >1 = error
    if result.returncode == 0:
        pytest.fail(
            "Layering violation: backend/app/core/ contains imports from "
            "app.modules.settings (modules must depend on core, not the "
            "reverse). Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_app_settings_imports_only_via_core_db_models() -> None:
    """`AppSetting` must only be imported from `app.core.db.models`.

    Catches reintroduction of the deleted `app.modules.settings.models` path
    (Phase 212 D-05). Anywhere across `backend/` that still names that module
    is a regression.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"app\.modules\.settings\.models",
        "backend/",
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: `app.modules.settings.models` is referenced after "
            "Phase 212 deleted it. Use `app.core.db.models` instead. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

Hard constraints on the test file:
- File must live at `backend/tests/test_layering.py` (not `backend/app/tests/...` and not at the repo root). The `parents[2]` math depends on this location.
- Both tests are decorated with `@pytest.mark.architecture` (D-07).
- Both tests use the `_has_git_metadata()` skip guard (RESEARCH.md Pitfall 4).
- The first test uses regex `^\s*(from|import)\s+app\.modules\.settings` — this catches both `from app.modules.settings.models import X`, `from app.modules.settings import Y`, and `import app.modules.settings.models`. Per Open Question 1, this is the narrow scope; do NOT broaden to `app.modules.` at this phase.
- The second test uses pattern `app\.modules\.settings\.models` (no anchoring) to catch any reference (string, comment, code). It is broader than the first test's scope but bounded to the now-deleted module path.

**Step 2 — Register the `architecture` marker in `backend/pyproject.toml`.**

Edit `backend/pyproject.toml`'s `[tool.pytest.ini_options]` `markers` list. The current 2-entry list (verified 2026-04-27 at lines 75-78):

```toml
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
]
```

Add a third entry (preserving the existing two verbatim and the closing `]`):

```toml
markers = [
    "perf: performance regression tests (deselected by default)",
    "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected to the test database (K2-PRE; fixture lives in tests/conftest.py)",
    "architecture: layering and boundary tests; opt-out locally with `-m 'not architecture'` (Phase 212 LAYER-01 guard)",
]
```

Hard constraints on pyproject.toml:
- Do NOT modify `addopts = "-m 'not perf'"`. Do NOT add `not architecture` to addopts. The architecture guard MUST run in the default CI invocation (D-07) — only `perf` tests are excluded by default.
- Do NOT touch any other section of `pyproject.toml` (dependencies, coverage, bandit, ruff, etc.).
- Use the Edit tool with `old_string` set to the EXACT current 4-line `markers = [...]` block and `new_string` set to the 5-line replacement. This guarantees no whitespace drift in `pyproject.toml`.

**Step 3 — Verify the guard works.**

After both file edits:

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v -m architecture
```

Expected: 2 passed (both tests detect zero violations because Plan 02 already removed every matching import). If a test FAILS:
- `test_core_does_not_import_from_settings_module` failing => Plan 02 missed a `core/` import; re-run `git grep "from app.modules.settings" -- backend/app/core/` to find the orphan.
- `test_app_settings_imports_only_via_core_db_models` failing => Plan 02 missed any caller in the broader inventory; re-run `git grep "app.modules.settings.models" -- backend/` to find it.

Also confirm the marker registration silenced the warning:

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v 2>&1 | grep -i "PytestUnknownMarkWarning" ; test $? -eq 1
```

Expected: zero output (no `PytestUnknownMarkWarning` emitted).

**Step 4 — Negative test discipline (manual; document only, do NOT commit the violation).**

Per VALIDATION.md V-10 and the "Manual-Only Verifications" section: as a one-time confidence check, temporarily edit `backend/app/core/persistent_config.py` to add the line `from app.modules.settings import router as _x` near the other imports, run `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_settings_module -v`, confirm it FAILS with a clear "Layering violation" message naming the file, then `git checkout backend/app/core/persistent_config.py` to revert. Document the result (pass-on-revert, fail-on-introduction) in the plan SUMMARY. DO NOT commit the violation. This step is optional in CI; it is a one-shot discipline check during local development.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && test -f backend/tests/test_layering.py && grep -q "architecture: layering" backend/pyproject.toml && (cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short -q) && (cd backend && uv run pytest tests/test_layering.py -v 2>&1 | grep -c "PytestUnknownMarkWarning" | tr -d ' ' | ( read n; test "$n" = "0" ))</automated>
  </verify>
  <acceptance_criteria>
    - File `backend/tests/test_layering.py` exists.
    - The file contains a function named `test_core_does_not_import_from_settings_module` decorated with `@pytest.mark.architecture`.
    - The file contains a function named `test_app_settings_imports_only_via_core_db_models` decorated with `@pytest.mark.architecture`.
    - The file contains a `_has_git_metadata()` helper and BOTH tests call `pytest.skip(...)` when it returns False (RESEARCH.md Pitfall 4).
    - `cd backend && uv run pytest tests/test_layering.py -v -m architecture` passes (2 passed, 0 failed, 0 errors).
    - `cd backend && uv run pytest tests/test_layering.py -v 2>&1 | grep "PytestUnknownMarkWarning"` returns no matches (the marker is registered).
    - `grep -F 'architecture: layering' backend/pyproject.toml` returns exactly one match.
    - `grep -F "addopts = \"-m 'not perf'\"" backend/pyproject.toml` still returns exactly one match (addopts is unchanged — D-07).
    - `cd backend && uv run pytest -m 'not architecture' --collect-only -q tests/test_layering.py 2>&1 | grep -q "no tests ran\|0 selected"` (the architecture tests are excluded when explicitly de-selected — proves D-07 opt-out works).
  </acceptance_criteria>
  <done>
    Architecture guard is in place, runs by default in CI, can be opt-out locally per D-07, and currently passes (because Plan 02 closed LAYER-01). Future reintroduction of `from app.modules.settings` under `backend/app/core/` will fail this test loudly with a clear filename in the failure message.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

This plan adds a CI guard test and a marker registration. No new code paths are introduced into the production runtime; the test file is collected only by pytest and never imported by `app/`. No new trust boundaries.

| Boundary | Description |
|----------|-------------|
| (none in app runtime) | Test-only addition; no impact on production trust boundaries. |
| Developer-vs-CI (existing) | The `architecture` marker provides a controlled opt-out for local TDD loops; the guard still runs in CI's default invocation. This is the audit-grade "no silent regression" boundary. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-212-02 | E (Elevation of Privilege via guard bypass) | Architecture guard test | mitigate | The marker `architecture` is opt-out, not opt-in. CI runs `pytest -m 'not perf'` which INCLUDES architecture tests by default. A contributor who wishes to bypass the guard would have to either (a) add `not architecture` to `addopts` (caught by `pyproject.toml` review in PR), (b) add a `# noqa` workaround that the regex doesn't catch (the regex is anchored to start-of-line `^\s*(from\|import)`, so any reasonable reintroduction is caught), or (c) split the import path across lines (Python disallows multi-line `from` imports without parens; even with parens, the start of the line still matches). The negative-test discipline in Step 4 verifies the guard fires loudly when the violation is introduced. |
| T-212-03 | INFO — guard test fragility | `_has_git_metadata()` skip | accept | If a CI runner ever runs this test without `.git/`, the test silently skips rather than failing; we accept this because (a) GitHub Actions `actions/checkout@v4` always provides `.git/`, (b) Phase 218's audit re-run is the ultimate proof the guard is effective regardless of runner state, and (c) RESEARCH.md confirmed `.dockerignore` is not present at the repo root, so docker-compose-based tests do see `.git/`. The skip path is a safety belt, not a primary control. |
</threat_model>

<verification>
- `cd backend && uv run pytest tests/test_layering.py -v -m architecture` exits 0 with 2 passed.
- `cd backend && uv run pytest tests/test_layering.py -v` (no `-m`) ALSO exits 0 with 2 passed (architecture tests run by default per D-07).
- `cd backend && uv run pytest tests/test_layering.py -v -m 'not architecture'` exits 0 but reports 0 tests collected (proves the opt-out works).
- `pyproject.toml` shows the new `architecture: layering ...` marker entry; `addopts` is unchanged.
- No `PytestUnknownMarkWarning` is emitted when `pytest tests/test_layering.py` runs.
</verification>

<success_criteria>
- The audit's "Layering" finding for `core/persistent_config.py:30` and `core/public_urls.py:14` cannot silently re-emerge: any reintroduction triggers a clear, named test failure on the next pytest run.
- The guard is opt-out for local dev (D-07) but mandatory in default CI invocation.
- The marker is registered cleanly (no `PytestUnknownMarkWarning`).
- The narrow scope (just `from app.modules.settings`) avoids false positives from Phase 213 / 214 territory (Open Question 1 / RESEARCH.md confirmation that `core/persistent_config.py` still has unrelated `from app.modules.audit` and `from app.modules.auth` imports today).
</success_criteria>

<output>
After completion, create `.planning/phases/212-core-settings-decouple/212-03-SUMMARY.md` documenting:
- The two test functions added and their pass/fail status against the post-Plan 02 codebase.
- The `pyproject.toml` diff (3-line markers list -> 4-line markers list; `addopts` untouched).
- The negative-test discipline result (Step 4): pass-on-revert, fail-on-introduction. Include a snippet of the failure message to confirm the guard names the offending file.
- A note that the guard scope is NARROW (`from app.modules.settings` only) and references Open Question 1 in 212-RESEARCH.md for the broadening plan in Phase 218.
</output>
